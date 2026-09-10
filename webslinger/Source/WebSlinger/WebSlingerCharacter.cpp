#include "WebSlingerCharacter.h"

#include "CableComponent.h"
#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/World.h"
#include "WebShooterComponent.h"
#include "WebSlingerMovementComponent.h"

AWebSlingerCharacter::AWebSlingerCharacter(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer.SetDefaultSubobjectClass<UWebSlingerMovementComponent>(ACharacter::CharacterMovementComponentName))
{
	PrimaryActorTick.bCanEverTick = true;

	GetCapsuleComponent()->InitCapsuleSize(38.f, 90.f);

	bUseControllerRotationYaw = true;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;

	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("FirstPersonCamera"));
	Camera->SetupAttachment(GetCapsuleComponent());
	Camera->SetRelativeLocation(FVector(0.f, 0.f, 70.f));
	// Driven by hand in Tick. bUsePawnControlRotation would take the whole
	// rotation each frame and stamp out the roll that sells a swing.
	Camera->bUsePawnControlRotation = false;
	Camera->FieldOfView = BaseFOV;

	WebShooter = CreateDefaultSubobject<UWebShooterComponent>(TEXT("WebShooter"));
	WebShooter->SetupAttachment(Camera);

	WebCable = CreateDefaultSubobject<UCableComponent>(TEXT("WebCable"));
	WebCable->SetupAttachment(Camera);
	WebCable->bAttachStart = true;
	// The far end is a fixed world point, not a component, so it is written
	// directly each frame by the shooter.
	WebCable->bAttachEnd = false;
	WebCable->NumSegments = 12;
	WebCable->SolverIterations = 8;
	WebCable->CableWidth = 3.f;
	WebCable->CableGravityScale = 0.15f;
	WebCable->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	WebCable->SetVisibility(false);

	// The line should leave from roughly wrist height, not the bridge of the nose.
	WebCable->SetRelativeLocation(FVector(20.f, 18.f, -18.f));

	GetMesh()->SetVisibility(false);
}

void AWebSlingerCharacter::BeginPlay()
{
	Super::BeginPlay();
	if (WebShooter)
	{
		WebShooter->SetCable(WebCable);
	}
}

UWebSlingerMovementComponent* AWebSlingerCharacter::GetSlingerMovement() const
{
	return Cast<UWebSlingerMovementComponent>(GetCharacterMovement());
}

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------

void AWebSlingerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);
	check(PlayerInputComponent);

	PlayerInputComponent->BindAxis("MoveForward", this, &AWebSlingerCharacter::MoveForward);
	PlayerInputComponent->BindAxis("MoveRight", this, &AWebSlingerCharacter::MoveRight);
	PlayerInputComponent->BindAxis("Turn", this, &AWebSlingerCharacter::Turn);
	PlayerInputComponent->BindAxis("LookUp", this, &AWebSlingerCharacter::LookUp);
	PlayerInputComponent->BindAxis("TurnRate", this, &AWebSlingerCharacter::TurnAtRate);
	PlayerInputComponent->BindAxis("LookUpRate", this, &AWebSlingerCharacter::LookUpAtRate);
	PlayerInputComponent->BindAxis("Reel", this, &AWebSlingerCharacter::Reel);

	PlayerInputComponent->BindAction("FireWeb", IE_Pressed, this, &AWebSlingerCharacter::OnFireWebPressed);
	PlayerInputComponent->BindAction("FireWeb", IE_Released, this, &AWebSlingerCharacter::OnFireWebReleased);
	PlayerInputComponent->BindAction("ZipTo", IE_Pressed, this, &AWebSlingerCharacter::OnZipPressed);
	PlayerInputComponent->BindAction("WallCrawl", IE_Pressed, this, &AWebSlingerCharacter::OnWallCrawlPressed);
	PlayerInputComponent->BindAction("WallCrawl", IE_Released, this, &AWebSlingerCharacter::OnWallCrawlReleased);
	PlayerInputComponent->BindAction("Jump", IE_Pressed, this, &ACharacter::Jump);
	PlayerInputComponent->BindAction("Jump", IE_Released, this, &ACharacter::StopJumping);
}

void AWebSlingerCharacter::MoveForward(float Value)
{
	if (FMath::IsNearlyZero(Value) || !Controller)
	{
		return;
	}

	const UWebSlingerMovementComponent* Move = GetSlingerMovement();
	if (Move && (Move->IsSwinging() || Move->IsWallCrawling()))
	{
		// Airborne and on walls, steering is where the camera points, including
		// pitch. On the ground it stays flat so looking down does not slow you.
		AddMovementInput(Camera->GetForwardVector(), Value);
		return;
	}

	const FRotator YawOnly(0.f, Controller->GetControlRotation().Yaw, 0.f);
	AddMovementInput(FRotationMatrix(YawOnly).GetUnitAxis(EAxis::X), Value);
}

void AWebSlingerCharacter::MoveRight(float Value)
{
	if (FMath::IsNearlyZero(Value) || !Controller)
	{
		return;
	}

	const UWebSlingerMovementComponent* Move = GetSlingerMovement();
	if (Move && Move->IsWallCrawling())
	{
		AddMovementInput(Camera->GetRightVector(), Value);
		return;
	}

	const FRotator YawOnly(0.f, Controller->GetControlRotation().Yaw, 0.f);
	AddMovementInput(FRotationMatrix(YawOnly).GetUnitAxis(EAxis::Y), Value);
}

void AWebSlingerCharacter::Turn(float Value)      { AddControllerYawInput(Value); }
void AWebSlingerCharacter::LookUp(float Value)    { AddControllerPitchInput(Value); }

void AWebSlingerCharacter::TurnAtRate(float Value)
{
	AddControllerYawInput(Value * TurnRateDegrees * GetWorld()->GetDeltaSeconds());
}

void AWebSlingerCharacter::LookUpAtRate(float Value)
{
	AddControllerPitchInput(-Value * LookRateDegrees * GetWorld()->GetDeltaSeconds());
}

void AWebSlingerCharacter::Reel(float Value)
{
	if (UWebSlingerMovementComponent* Move = GetSlingerMovement())
	{
		Move->SetReelInput(Value);
	}
}

void AWebSlingerCharacter::OnFireWebPressed()
{
	if (WebShooter)
	{
		WebShooter->FireWeb();
	}
}

void AWebSlingerCharacter::OnFireWebReleased()
{
	if (WebShooter)
	{
		WebShooter->ReleaseWeb();
	}
}

void AWebSlingerCharacter::OnZipPressed()
{
	if (WebShooter)
	{
		WebShooter->ZipToTarget();
	}
}

void AWebSlingerCharacter::OnWallCrawlPressed()
{
	bWantsToCrawl = true;
	TryStartWallCrawl();
}

void AWebSlingerCharacter::OnWallCrawlReleased()
{
	bWantsToCrawl = false;
	if (UWebSlingerMovementComponent* Move = GetSlingerMovement())
	{
		Move->EndWallCrawl();
	}
}

// ---------------------------------------------------------------------------
// Wall crawling
// ---------------------------------------------------------------------------

bool AWebSlingerCharacter::TryStartWallCrawl()
{
	UWebSlingerMovementComponent* Move = GetSlingerMovement();
	UWorld* World = GetWorld();
	if (!Move || !World || Move->IsWallCrawling())
	{
		return false;
	}

	const FVector Origin = GetActorLocation();
	const float Radius = GetCapsuleComponent()->GetScaledCapsuleRadius();

	// Ordered by preference: where you are looking, then where you are facing,
	// then the sides, then above. First hit wins, so intent beats geometry.
	const TArray<FVector> Directions = {
		Camera->GetForwardVector(),
		GetActorForwardVector(),
		GetActorRightVector(),
		-GetActorRightVector(),
		-GetActorForwardVector(),
		FVector::UpVector,
	};

	FCollisionQueryParams Params(SCENE_QUERY_STAT(WallCrawlSearch), false, this);

	for (const FVector& Dir : Directions)
	{
		const FVector Flat = Dir.GetSafeNormal();
		if (Flat.IsNearlyZero())
		{
			continue;
		}

		FHitResult Hit;
		const bool bHit = World->SweepSingleByChannel(
			Hit, Origin, Origin + Flat * (Radius + CrawlSearchDistance), FQuat::Identity,
			ECC_Visibility, FCollisionShape::MakeSphere(Radius * 0.6f), Params);

		if (bHit && Move->BeginWallCrawl(Hit))
		{
			return true;
		}
	}

	return false;
}

// ---------------------------------------------------------------------------
// Tick
// ---------------------------------------------------------------------------

void AWebSlingerCharacter::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);

	// Holding crawl against a wall you have just landed on should stick, so
	// keep retrying rather than only testing on the key press.
	if (bWantsToCrawl)
	{
		const UWebSlingerMovementComponent* Move = GetSlingerMovement();
		if (Move && !Move->IsWallCrawling() && !Move->IsSwinging())
		{
			TryStartWallCrawl();
		}
	}

	UpdateCameraFeel(DeltaTime);
}

void AWebSlingerCharacter::UpdateCameraFeel(float DeltaTime)
{
	if (!Camera || !Controller)
	{
		return;
	}

	const UWebSlingerMovementComponent* Move = GetSlingerMovement();

	// Bank into the anchor. The horizon tipping through the arc is what tells
	// the player they are on a pendulum and not on a rail.
	const float TargetRoll = Move ? Move->GetSwingLean() * MaxSwingRoll : 0.f;
	CurrentRoll = FMath::FInterpTo(CurrentRoll, TargetRoll, DeltaTime, RollInterpSpeed);

	const FRotator Control = GetControlRotation();
	Camera->SetWorldRotation(FRotator(Control.Pitch, Control.Yaw, CurrentRoll));

	// Speed reads as FOV. Interpolated, because snapping it is nauseating.
	const float MaxSpeed = Move ? FMath::Max(1.f, Move->MaxSwingSpeed) : 1.f;
	const float SpeedAlpha = FMath::Clamp(GetVelocity().Size() / MaxSpeed, 0.f, 1.f);
	const float TargetFOV = BaseFOV + SpeedFOVBoost * SpeedAlpha;
	Camera->FieldOfView = FMath::FInterpTo(Camera->FieldOfView, TargetFOV, DeltaTime, FOVInterpSpeed);
}
