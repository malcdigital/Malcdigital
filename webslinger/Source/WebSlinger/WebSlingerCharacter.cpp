#include "WebSlingerCharacter.h"

#include "CableComponent.h"
#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "Engine/LocalPlayer.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"
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

	BuildInputAssets();
	ApplyMappingContext();
}

UWebSlingerMovementComponent* AWebSlingerCharacter::GetSlingerMovement() const
{
	return Cast<UWebSlingerMovementComponent>(GetCharacterMovement());
}

// ---------------------------------------------------------------------------
// Input setup
//
// Enhanced Input normally wants an InputMappingContext and one InputAction per
// binding, all as .uasset files. Those are binary and cannot live in a text
// repository, so they are constructed here instead. Identical behaviour, and
// the project still builds from a bare clone with no content folder.
// ---------------------------------------------------------------------------

namespace
{
	/** Create a runtime InputAction of the given value type. */
	UInputAction* MakeAction(UObject* Outer, EInputActionValueType Type, const TCHAR* Name)
	{
		UInputAction* Action = NewObject<UInputAction>(Outer, Name);
		Action->ValueType = Type;
		return Action;
	}

	/** Map a key, optionally inverted - W/S and A/D share one axis each. */
	void Map(UInputMappingContext* Context, UInputAction* Action, const FKey& Key, bool bNegate = false)
	{
		FEnhancedActionKeyMapping& Mapping = Context->MapKey(Action, Key);
		if (bNegate)
		{
			Mapping.Modifiers.Add(NewObject<UInputModifierNegate>(Context));
		}
	}
}

void AWebSlingerCharacter::BuildInputAssets()
{
	if (InputContext)
	{
		return;
	}

	InputContext = NewObject<UInputMappingContext>(this, TEXT("WebSlingerMappingContext"));

	ActMoveForward = MakeAction(this, EInputActionValueType::Axis1D, TEXT("IA_MoveForward"));
	ActMoveRight   = MakeAction(this, EInputActionValueType::Axis1D, TEXT("IA_MoveRight"));
	ActTurn        = MakeAction(this, EInputActionValueType::Axis1D, TEXT("IA_Turn"));
	ActLookUp      = MakeAction(this, EInputActionValueType::Axis1D, TEXT("IA_LookUp"));
	ActTurnRate    = MakeAction(this, EInputActionValueType::Axis1D, TEXT("IA_TurnRate"));
	ActLookUpRate  = MakeAction(this, EInputActionValueType::Axis1D, TEXT("IA_LookUpRate"));
	ActReel        = MakeAction(this, EInputActionValueType::Axis1D, TEXT("IA_Reel"));
	ActFireWeb     = MakeAction(this, EInputActionValueType::Boolean, TEXT("IA_FireWeb"));
	ActZip         = MakeAction(this, EInputActionValueType::Boolean, TEXT("IA_Zip"));
	ActJump        = MakeAction(this, EInputActionValueType::Boolean, TEXT("IA_Jump"));
	ActWallCrawl   = MakeAction(this, EInputActionValueType::Boolean, TEXT("IA_WallCrawl"));

	Map(InputContext, ActMoveForward, EKeys::W);
	Map(InputContext, ActMoveForward, EKeys::S, /*bNegate*/ true);
	Map(InputContext, ActMoveForward, EKeys::Gamepad_LeftY);
	Map(InputContext, ActMoveRight, EKeys::D);
	Map(InputContext, ActMoveRight, EKeys::A, /*bNegate*/ true);
	Map(InputContext, ActMoveRight, EKeys::Gamepad_LeftX);

	// Mouse deltas are already frame-scaled; stick values are not, so they get
	// their own actions and are multiplied by delta time in the handlers.
	Map(InputContext, ActTurn, EKeys::MouseX);
	Map(InputContext, ActLookUp, EKeys::MouseY, /*bNegate*/ true);
	Map(InputContext, ActTurnRate, EKeys::Gamepad_RightX);
	Map(InputContext, ActLookUpRate, EKeys::Gamepad_RightY);

	Map(InputContext, ActReel, EKeys::MouseWheelAxis);
	Map(InputContext, ActReel, EKeys::E);
	Map(InputContext, ActReel, EKeys::Q, /*bNegate*/ true);

	Map(InputContext, ActFireWeb, EKeys::LeftMouseButton);
	Map(InputContext, ActFireWeb, EKeys::Gamepad_RightTrigger);
	Map(InputContext, ActZip, EKeys::RightMouseButton);
	Map(InputContext, ActZip, EKeys::Gamepad_LeftTrigger);
	Map(InputContext, ActJump, EKeys::SpaceBar);
	Map(InputContext, ActJump, EKeys::Gamepad_FaceButton_Bottom);
	Map(InputContext, ActWallCrawl, EKeys::LeftShift);
	Map(InputContext, ActWallCrawl, EKeys::Gamepad_LeftShoulder);
}

void AWebSlingerCharacter::ApplyMappingContext()
{
	const APlayerController* PC = Cast<APlayerController>(GetController());
	if (!PC || !InputContext)
	{
		return;
	}

	if (UEnhancedInputLocalPlayerSubsystem* Subsystem =
			ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
	{
		Subsystem->AddMappingContext(InputContext, 0);
	}
}

void AWebSlingerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);

	BuildInputAssets();
	ApplyMappingContext();

	UEnhancedInputComponent* Input = Cast<UEnhancedInputComponent>(PlayerInputComponent);
	if (!Input)
	{
		// Project settings have been switched back to the legacy input component.
		UE_LOG(LogTemp, Error, TEXT("WebSlinger needs the Enhanced Input component. "
			"Check DefaultInputComponentClass in Project Settings > Input."));
		return;
	}

	Input->BindAction(ActMoveForward, ETriggerEvent::Triggered, this, &AWebSlingerCharacter::OnMoveForward);
	Input->BindAction(ActMoveRight, ETriggerEvent::Triggered, this, &AWebSlingerCharacter::OnMoveRight);
	Input->BindAction(ActTurn, ETriggerEvent::Triggered, this, &AWebSlingerCharacter::OnTurn);
	Input->BindAction(ActLookUp, ETriggerEvent::Triggered, this, &AWebSlingerCharacter::OnLookUp);
	Input->BindAction(ActTurnRate, ETriggerEvent::Triggered, this, &AWebSlingerCharacter::OnTurnRate);
	Input->BindAction(ActLookUpRate, ETriggerEvent::Triggered, this, &AWebSlingerCharacter::OnLookUpRate);

	// Reel holds a value on the movement component, so it needs an explicit
	// reset when the key comes up - unlike movement input, which is consumed
	// and cleared every frame.
	Input->BindAction(ActReel, ETriggerEvent::Triggered, this, &AWebSlingerCharacter::OnReel);
	Input->BindAction(ActReel, ETriggerEvent::Completed, this, &AWebSlingerCharacter::OnReelReleased);
	Input->BindAction(ActReel, ETriggerEvent::Canceled, this, &AWebSlingerCharacter::OnReelReleased);

	Input->BindAction(ActFireWeb, ETriggerEvent::Started, this, &AWebSlingerCharacter::OnFireWebPressed);
	Input->BindAction(ActFireWeb, ETriggerEvent::Completed, this, &AWebSlingerCharacter::OnFireWebReleased);
	Input->BindAction(ActZip, ETriggerEvent::Started, this, &AWebSlingerCharacter::OnZipPressed);
	Input->BindAction(ActJump, ETriggerEvent::Started, this, &AWebSlingerCharacter::OnJumpPressed);
	Input->BindAction(ActJump, ETriggerEvent::Completed, this, &AWebSlingerCharacter::OnJumpReleased);
	Input->BindAction(ActWallCrawl, ETriggerEvent::Started, this, &AWebSlingerCharacter::OnWallCrawlPressed);
	Input->BindAction(ActWallCrawl, ETriggerEvent::Completed, this, &AWebSlingerCharacter::OnWallCrawlReleased);
}

// ---------------------------------------------------------------------------
// Input handlers
// ---------------------------------------------------------------------------

void AWebSlingerCharacter::OnMoveForward(const FInputActionValue& Value)
{
	const float Scale = Value.Get<float>();
	if (FMath::IsNearlyZero(Scale) || !Controller)
	{
		return;
	}

	const UWebSlingerMovementComponent* Move = GetSlingerMovement();
	if (Move && (Move->IsSwinging() || Move->IsWallCrawling()))
	{
		// Airborne and on walls, steering is where the camera points, including
		// pitch. On the ground it stays flat so looking down does not slow you.
		AddMovementInput(Camera->GetForwardVector(), Scale);
		return;
	}

	const FRotator YawOnly(0.f, Controller->GetControlRotation().Yaw, 0.f);
	AddMovementInput(FRotationMatrix(YawOnly).GetUnitAxis(EAxis::X), Scale);
}

void AWebSlingerCharacter::OnMoveRight(const FInputActionValue& Value)
{
	const float Scale = Value.Get<float>();
	if (FMath::IsNearlyZero(Scale) || !Controller)
	{
		return;
	}

	const UWebSlingerMovementComponent* Move = GetSlingerMovement();
	if (Move && Move->IsWallCrawling())
	{
		AddMovementInput(Camera->GetRightVector(), Scale);
		return;
	}

	const FRotator YawOnly(0.f, Controller->GetControlRotation().Yaw, 0.f);
	AddMovementInput(FRotationMatrix(YawOnly).GetUnitAxis(EAxis::Y), Scale);
}

void AWebSlingerCharacter::OnTurn(const FInputActionValue& Value)
{
	AddControllerYawInput(Value.Get<float>() * MouseSensitivity);
}

void AWebSlingerCharacter::OnLookUp(const FInputActionValue& Value)
{
	AddControllerPitchInput(Value.Get<float>() * MouseSensitivity);
}

void AWebSlingerCharacter::OnTurnRate(const FInputActionValue& Value)
{
	AddControllerYawInput(Value.Get<float>() * TurnRateDegrees * GetWorld()->GetDeltaSeconds());
}

void AWebSlingerCharacter::OnLookUpRate(const FInputActionValue& Value)
{
	AddControllerPitchInput(-Value.Get<float>() * LookRateDegrees * GetWorld()->GetDeltaSeconds());
}

void AWebSlingerCharacter::OnReel(const FInputActionValue& Value)
{
	if (UWebSlingerMovementComponent* Move = GetSlingerMovement())
	{
		Move->SetReelInput(Value.Get<float>());
	}
}

void AWebSlingerCharacter::OnReelReleased()
{
	if (UWebSlingerMovementComponent* Move = GetSlingerMovement())
	{
		Move->SetReelInput(0.f);
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

void AWebSlingerCharacter::OnJumpPressed()  { Jump(); }
void AWebSlingerCharacter::OnJumpReleased() { StopJumping(); }

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
